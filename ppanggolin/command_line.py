#!/usr/bin/env python3
# -*- coding: iso-8859-1 -*-

from collections import defaultdict, OrderedDict
from ordered_set import OrderedSet
import networkx as nx
import logging
import sys
import os
import argparse
from random import shuffle, sample
from tqdm import tqdm
tqdm.monitor_interval = 0
from concurrent.futures import ProcessPoolExecutor, as_completed
from time import gmtime, strftime, time
import subprocess
import pkg_resources
import traceback
import shutil
from .ppanggolin import *
from .utils import *

### PATH AND FILE NAME
OUTPUTDIR                   = None 
TMP_DIR                     = None
NEM_DIR                     = "/NEM_results/"
FIGURE_DIR                  = "/figures/"
PROJECTION_DIR              = "/projections/"
EVOLUTION_DIR               = "/evolutions/"
PARTITION_DIR               = "/partitions/"
GRAPH_FILE_PREFIX           = "/graph"
MATRIX_FILES_PREFIX         = "/matrix"
USHAPE_PLOT_PREFIX          = "/Ushaped_plot"
MATRIX_PLOT_PREFIX          = "/presence_absence_matrix_plot"
EVOLUTION_CURVE_PREFIX      = "/evolution_curve"
EVOLUTION_STATS_FILE_PREFIX = "/evol_stats"
SUMMARY_STATS_FILE_PREFIX   = "/summary_stats"
SCRIPT_R_FIGURE             = "/generate_plots.R"

def plot_Rscript(script_outfile, verbose=True):
    """
    """
    rscript = "#!/usr/bin/env R\n"+("options(warn=-1)\n" if not verbose else "")+"""
options(show.error.locations = TRUE)

library("ggplot2")
library("reshape2")

color_chart = c(pangenome="black", "accessory"="#EB37ED", "core_exact" ="#FF2828", shell = "#00D860", persistent="#F7A507", cloud = "#79DEFF")

########################### START U SHAPED PLOT #################################

binary_matrix         <- read.table('"""+OUTPUTDIR+MATRIX_FILES_PREFIX+""".Rtab', header=TRUE, sep='\\t', check.names = FALSE)
data_header           <- c("Gene","Non-unique Gene name","Annotation","No. isolates","No. sequences","Avg sequences per isolate","Accessory Fragment","Genome Fragment","Order within Fragment","Accessory Order with Fragment","QC","Min group size nuc","Max group size nuc","Avg group size nuc") 
family_data           <- binary_matrix[,colnames(binary_matrix) %in% data_header]
binary_matrix         <- binary_matrix[,!(colnames(binary_matrix) %in% data_header)]
binary_matrix[binary_matrix>1] <- 1
occurences            <- rowSums(binary_matrix)
classification_vector <- family_data[,2]

c = data.frame(nb_org = occurences, partition = classification_vector)

plot <- ggplot(data = c) + 
    geom_bar(aes_string(x = "nb_org", fill = "partition")) +
    scale_fill_manual(name = "partition", values = color_chart, breaks=c("persistent","shell","cloud")) +
    scale_x_discrete(limits = seq(1, ncol(binary_matrix))) +
    xlab("# of organisms in which each familly is present")+
    ylab("# of families")+
    ggplot2::theme(axis.text.x = element_text(angle = 90, hjust = 1, vjust = 0.5))

ggsave('"""+OUTPUTDIR+FIGURE_DIR+USHAPE_PLOT_PREFIX+""".pdf', device = "pdf", height= (par("din")[2]*1.5),plot)

########################### END U SHAPED PLOT #################################

########################### START PRESENCE/ABSENCE MATRIX #################################

nb_org                  <- ncol(binary_matrix)

binary_matrix_hclust    <- hclust(dist(t(binary_matrix), method="binary"))
binary_matrix           <- data.frame(binary_matrix,"NEM partitions" = classification_vector, occurences = occurences, check.names=FALSE)

binary_matrix[occurences == nb_org, "Former partitions"] <- "core_exact"
binary_matrix[occurences != nb_org, "Former partitions"] <- "accessory"
binary_matrix = binary_matrix[order(match(binary_matrix$"NEM partitions",c("persistent", "shell", "cloud")),
                                    match(binary_matrix$"Former partitions",c("core_exact", "accessory")),
                                    -binary_matrix$occurences),
                              c(binary_matrix_hclust$label[binary_matrix_hclust$order],"NEM partitions","Former partitions")]

binary_matrix$familles <- seq(1,nrow(binary_matrix))
data = melt(binary_matrix, id.vars=c("familles"))

colnames(data) = c("fam","org","value")

data$value <- factor(data$value, levels = c(1,0,"persistent", "shell", "cloud", "core_exact", "accessory"), labels = c("presence","absence","persistent", "shell", "cloud", "core_exact", "accessory"))

plot <- ggplot(data = data)+
        geom_raster(aes_string(x="org",y="fam", fill="value"))+
        scale_fill_manual(values = c("presence"="green","absence"="grey80",color_chart)) +
        theme(axis.text.x = element_text(angle = 90, hjust = 1, vjust = 0.5, size=1), panel.border = element_blank(), panel.background = element_blank())

ggsave('"""+OUTPUTDIR+FIGURE_DIR+MATRIX_PLOT_PREFIX+""".pdf', device = "pdf", plot)

########################### END PRESENCE/ABSENCE MATRIX #################################

########################### START EVOLUTION CURVE #################################

library("ggrepel")
library("data.table")
library("minpack.lm")

if (file.exists('"""+OUTPUTDIR+EVOLUTION_DIR+EVOLUTION_STATS_FILE_PREFIX+""".txt')){
    data <- read.csv('"""+OUTPUTDIR+EVOLUTION_DIR+EVOLUTION_STATS_FILE_PREFIX+""".txt', header = TRUE)
    data <- melt(data, id = "nb_org")
    colnames(data) <- c("nb_org","partition","value")

    final_state = data[data$nb_org == max(data$nb_org,na.rm=T),]
    final_state = final_state[!duplicated(final_state[,c("nb_org","partition")]), ]
    final <- structure(names = as.character(final_state$partition), as.integer(final_state$value))

    #gamma and kappa are calculated according to the Tettelin et al. 2008 approach
    median_by_nb_org <- setDT(data)[,list(med=as.numeric(median(value))), by=c("nb_org","partition")]
    colnames(median_by_nb_org) <- c("nb_org_comb","partition","med")

    for (part in as.character(final_state$partition)){
        regression  <- nlsLM(med~kapa*(nb_org_comb^gama),median_by_nb_org[which(median_by_nb_org$partition == part),],start=list(kapa=1000,gama=0))
        coefficient <- coef(regression)
        final_state[final_state$partition == part,"formula" ] <- paste0("F == ", format(coefficient["kapa"],decimal.mark = ",",digits =2),"~N^{",format(coefficient["gama"],digits =2),"}")
    }

    plot <- ggplot(data = data, aes_string(x="nb_org",y="value", colour = "partition"))+
            ggtitle(bquote(list("Rarefaction curve. Heap's law parameters based on Tettelin et al. 2008 approach", n == kappa~N^gamma)))+
            geom_smooth(data        = median_by_nb_org[median_by_nb_org$partition %in% c("pangenome","shell","cloud","accessory", "persistent", "core_exact") ,],# 
                        mapping     = aes_string(x="nb_org_comb",y="med",colour = "partition"),
                        method      = "nlsLM",
                        formula     = y~kapa*(x^gama),method.args =list(start=c(kapa=1000,gama=0)),
                        linetype    ="twodash",
                        size        = 1.5,
                        se          = FALSE,
                        show.legend = FALSE)+
            stat_summary(fun.ymin = function(z) { quantile(z,0.25) },  fun.ymax = function(z) { quantile(z,0.75) }, geom="ribbon", alpha=0.1,size=0.1, linetype="dashed", show.legend = FALSE)+
            stat_summary(fun.y=median, geom="line",size=0.5)+
            stat_summary(fun.y=median, geom="point",shape=4,size=1, show.legend = FALSE)+
            stat_summary(fun.ymax=max,fun.ymin=min,geom="errorbar",linetype="dotted",size=0.1,width=0.2)+
            scale_x_continuous(breaks = as.numeric(unique(data$nb_org)))+
            scale_y_continuous(limits=c(0,max(data$value,na.rm=T)), breaks = seq(0,max(data$value,na.rm=T),1000))+
            scale_colour_manual(name = "NEM partitioning", values = color_chart, breaks=names(sort(final, decreasing = TRUE)))+
            geom_label_repel(data = final_state, aes_string(x="nb_org", y="value", colour = "partition", label = "value"), show.legend = FALSE,
                      fontface = 'bold', fill = 'white',
                      box.padding = unit(0.35, "lines"),
                      point.padding = unit(0.5, "lines"),
                      segment.color = 'grey50',
                      nudge_x = 45) +
            geom_label_repel(data = final_state, aes(x = nb_org*0.9, y = value, label = formula), size = 2, parse = TRUE, show.legend = FALSE, segment.color = NA) + 
            xlab("# of organisms")+
            ylab("# of families")+
            ggplot2::theme(axis.text.x = element_text(angle = 90, hjust = 1, vjust = 0.5), panel.grid.minor = element_blank())
    
    ggsave('"""+OUTPUTDIR+FIGURE_DIR+EVOLUTION_CURVE_PREFIX+""".pdf', device = "pdf", width = (par("din")[1]*2) ,plot)

}
########################### END EVOLUTION CURVE #################################

########################### START PROJECTION #################################

for (org_csv in list.files(path = '"""+OUTPUTDIR+PROJECTION_DIR+"""', pattern = "*.csv$", full.names = T)){
    org_name <- tools::file_path_sans_ext(basename(org_csv))
    data <- read.csv(org_csv, header = T)
    if(org_name=="nb_genes"){
        data.melted = melt(data,id.var="org")
        colnames(data.melted) <- c("org","partition","nb_geness")
        is_outlier <- function(x) {
            return(x < quantile(x, 0.25) - 1.5 * IQR(x) | x > quantile(x, 0.75) + 1.5 * IQR(x))
        }
        data.melted_persistent = data.melted[data.melted$partition =="persistent",]
        data.melted_persistent <- data.melted_persistent[is_outlier(data.melted_persistent$nb_geness),]
        data.melted_shell = data.melted[data.melted$partition =="shell",]
        data.melted_shell <- data.melted_shell[is_outlier(data.melted_shell$nb_geness),]
        data.melted_cloud = data.melted[data.melted$partition =="cloud",]
        data.melted_cloud <- data.melted_cloud[is_outlier(data.melted_cloud$nb_geness),]
        data.melted_core_exact = data.melted[data.melted$partition =="core_exact",]
        data.melted_core_exact <- data.melted_core_exact[is_outlier(data.melted_core_exact$nb_geness),]
        data.melted_accessory = data.melted[data.melted$partition =="accessory",]
        data.melted_accessory <- data.melted_accessory[is_outlier(data.melted_accessory$nb_geness),]
        data.melted_pangenome = data.melted[data.melted$partition =="cloud",]
        data.melted_pangenome <- data.melted_pangenome[is_outlier(data.melted_pangenome$nb_geness),]

        plot = ggplot(data.melted)+
               ggtitle(paste0("number of genes resulting of the projection of the partionning on each organism (nb organism=", nrow(data),")"))+
               geom_boxplot(aes(x = partition,y = nb_geness, fill = partition))+
               geom_text_repel(data = rbind(data.melted_persistent,data.melted_shell,data.melted_cloud, data.melted_core_exact, data.melted_accessory, data.melted_pangenome),
                               aes(x=partition, y=nb_geness, label = org))+
               scale_fill_manual(name = "partitioning", values = color_chart)
    }
    else{
        data <- cbind(data, pos = seq(nrow(data)))

        max_degree_log2p1 <- max(apply(data,1,FUN = function(x){
                sum(log2(as.numeric(x[10:12])+1))
            }))

        ori <- which(data$ori == T, arr.ind=T)
        data$ori <- NULL

        duplicated_fam     <- unique(data[duplicated(data$family),"family"])
        data$family <- ifelse(data$family %in% duplicated_fam, data$family, NA)
        data$family = as.factor(data$family)
        colors_duplicated_fam <- rainbow(length(duplicated_fam))
        names(colors_duplicated_fam) <- duplicated_fam

        data_melted <- melt(data, id.var=c("contig", "gene","family","nb_copy_in_org","partition","pos"))
        data_melted$variable <- factor(data_melted$variable, levels = rev(c("persistent","shell","cloud")), ordered=TRUE)

        contig <- unique(data_melted$contig)
        contig_color <-  rainbow(length(contig))
        names(contig_color) <- contig

        data_melted$value <- log2(data_melted$value+1)
        plot = ggplot(data = data_melted)+
        ggtitle(paste0("plot corresponding to the file", org_name))+
        geom_bar(aes_string(x = "gene", y = "value", fill = "variable"),stat="identity", show.legend = FALSE)+
        scale_y_continuous(limits = c(-30, max_degree_log2p1), breaks = seq(0,ceiling(max_degree_log2p1)))+
        geom_hline(yintercept = 0)+
        geom_rect(aes_string(xmin ="pos-1/2", xmax = "pos+1/2", fill = "partition"), ymin = -10, ymax=-1, color = NA, show.legend = FALSE)+
        geom_hline(yintercept = -10)+
        geom_rect(aes_string(xmin ="pos-1/2", xmax = "pos+1/2", fill = "family"), ymin = -20, ymax=-11,  color = NA, show.legend = FALSE)+
        geom_hline(yintercept = -20)+
        geom_rect(aes_string(xmin ="pos-1/2", xmax = "pos+1/2", fill = "contig"), ymin = -30, ymax=-21,  color = NA)+
        geom_vline(xintercept = ori)+
        scale_fill_manual(values = c(color_chart,colors_duplicated_fam, contig_color), na.value = "grey80")+
        coord_polar()+
        ylab("log2(degree+1) of the families in wich each gene is")+
        theme(axis.line        = ggplot2::element_blank(),
              axis.text.x      = ggplot2::element_blank(),
              axis.ticks.x     = ggplot2::element_blank(),
              axis.title.x     = ggplot2::element_blank(),
              panel.background = ggplot2::element_blank(),
              panel.border     = ggplot2::element_blank(),
              panel.grid.major.x = ggplot2::element_blank(),
              panel.grid.minor.x = ggplot2::element_blank(),
              plot.background  = ggplot2::element_blank(),
              plot.margin      = grid::unit(c(0,0,0,0), "cm"),
              panel.spacing    = grid::unit(c(0,0,0,0), "cm"))
    }
    ggsave(paste0('"""+OUTPUTDIR+FIGURE_DIR+"""',org_name,'.pdf'), device = "pdf", height= 40, width = 49, plot)

}
########################### END PROJECTION #################################

    """
    logging.getLogger().info("Writing R script generating plot")
    with open(script_outfile,"w") as script_file:
        script_file.write(rscript)

#### START - NEED TO BE AT THE HIGHEST LEVEL OF THE MODULE TO ALLOW MULTIPROCESSING

shuffled_comb = []
evol = None
pan = None
options = None
EVOLUTION = None

def resample(index):
    global shuffled_comb
    nem_dir_path    = TMP_DIR+EVOLUTION_DIR+"/nborg"+str(len(shuffled_comb[index]))+"_"+str(index)
    stats = pan.partition(nem_dir_path    = nem_dir_path,
                          organisms       = shuffled_comb[index],
                          beta            = options.beta_smoothing[0],
                          free_dispersion = options.free_dispersion,
                          chunck_size     = options.chunck_size[0],
                          inplace         = False,
                          just_stats      = True,
                          nb_threads      = 1)
    shutil.rmtree(nem_dir_path)
    evol.write(",".join([str(len(shuffled_comb[index])),
                          str(stats["persistent"]) if stats["undefined"] == 0 else "NA",
                          str(stats["shell"]) if stats["undefined"] == 0 else "NA",
                          str(stats["cloud"]) if stats["undefined"] == 0 else "NA",
                          str(stats["core_exact"]),
                          str(stats["accessory"]),
                          str(stats["core_exact"]+stats["accessory"])])+"\n")
    evol.flush()

# def replication(index):
#     subset = random.sample(pan.organisms, 2)
#     old_res = None
#     before_pangenome = None
#     before_shell = None
#     for i in range(pan.nb_organisms):
#         res = pan.partition(subset,just_stats=False,inplace=False)
#         if old_res is not None:
#             pangenome    = set(res["accessory"]+res["core_exact"])
#             new_families = pangenome - before_pangenome
#             new_shell    = set(res["shell"]) - before_shell
#     subset.add(random.sample(pan.organisms-subset,STEP))
#     evol.write("\t".join([str(len(shuffled_comb[index])),
#                           str(stats["persistent"]) if stats["undefined"] == 0 else "NA",
#                           str(stats["shell"]) if stats["undefined"] == 0 else "NA",
#                           str(stats["cloud"]) if stats["undefined"] == 0 else "NA",
#                           str(stats["core_exact"]),
#                           str(stats["accessory"]),
#                           str(stats["core_exact"]+stats["accessory"])])+"\n")
#     evol.flush()

    if options.delete_nem_intermediate_files:
        shutil.rmtree(TMP_DIR+EVOLUTION_DIR+"/nborg"+str(len(shuffled_comb[index]))+"_"+str(index))

#### END - NEED TO BE AT THE HIGHEST LEVEL OF THE MODULE TO ALLOW MULTIPROCESSING

def __main__():
    parser = argparse.ArgumentParser(prog = "ppanggolin",
                                     description='Build a partitioned pangenome graph from annotated genomes (GFF files) and gene families (TSV files). Reserved words are: '+' '.join(RESERVED_WORDS), 
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-?', '--version', action='version', version=pkg_resources.get_distribution("ppanggolin").version)
    parser.add_argument('-o', '--organisms', type=argparse.FileType('r'), nargs=1, metavar=('ORGANISMS_FILE'), help="""
    File: A tab-delimited file containing at least 2 mandatory fields by row and as many optional fields as the number of well assembled circular contigs. 
    Each row corresponds to an organism to be added to the pangenome.
    The first field is the organism ID.
    The organism ID can be any string but must be unique and can't contain any space, quote, double quote and reserved word.
    The second field is the gff file containing the annotations associated to the organism. 
    This path can be absolute or relative. 
    The gff file must contain an ID feature for each CDS.
    The contig ID and gene ID can be any string but must be unique and can't contain any space, quote, double quote, pipe and reserved words.
    (optional). The next fields contain the name of perfectly assembled circular contigs. 
    In this case, it is mandatory to provide the contig size in the gff files either by adding a "region" feature having the correct contig ID attribute or using a '##sequence-region' pragma.
    """, required=True)
    parser.add_argument('-gf', '--gene_families', type=argparse.FileType('r'), nargs=1, metavar=('FAMILIES_FILE'), help="""
    File: A tab-delimited file containing the gene families. Each row contains at least 2 fields.
    The first field is the family ID. The further fields are the gene IDs associated with this family.
    The family ID can be any string but must be unique and can't contain any space, quote, double quote and reserved word.
    Gene IDs can be any string corresponding to the ID features in the gff files. They must be uniques and can't contain any spaces, quote, double quote and reserved words.
    """,  required=True)
    parser.add_argument('-od', '--output_directory', type=str, nargs=1, default=["PPanGGOLiN_outputdir_"+strftime("%Y-%m-%d_%H.%M.%S", gmtime())], metavar=('OUTPUT_DIR'), help="""
    Dir: The output directory""")
    parser.add_argument('-td', '--temporary_directory', type=str, nargs=1, default=["/tmp/PPanGGOLiN_outputdir_"+strftime("%Y-%m-%d_%H.%M.%S", gmtime())], metavar=('TMP_DIR'), help="""
    Dir: Temporary directory to store nem intermediate files""")
    parser.add_argument('-f', '--force', action="store_true", help="""
    Flag: Force overwriting existing output directory""")
    parser.add_argument('-r', '--remove_high_copy_number_families', type=int, nargs=1, default=[0], metavar=('REPETITION_THRESHOLD'), help="""
    Positive Number: Remove families having a number of copy of gene in a single family above or equal to this threshold in at least one organism (0 or negative values are ignored). 
    """)#When -update is set, only work on new organisms added
    parser.add_argument('-s', '--infer_singletons', default=False, action="store_true", help="""
    Flag: If a gene id found in a gff file is absent of the gene families file, the singleton will be automatically infered as a gene families having a single element. 
    if this argument is not set, the program will raise KeyError exception if a gene id found in a gff file is absent of the gene families file.""")
    #    parser.add_argument("-up", "--update", default = None, type=argparse.FileType('r'), nargs=1, help="""
    # Pangenome Graph to be updated (in gexf format)""")
    parser.add_argument("-u", "--untangle", type=int, default = 0, nargs=1, help="""
    Flag: (in test) max size of the untangled paths to be untangled""")
    parser.add_argument("-b", "--beta_smoothing", default = [float("0.5")], type=float, nargs=1, metavar=('BETA_VALUE'), help = """
    Positive Number: This option determines the strength of the smoothing (:math:beta) of the partitions based on the graph topology (using a Markov Random Field). 
    b must be a positive float, b = 0.0 means to discard spatial smoothing and 1.00 means strong smoothing (can be more but it is not advised).
    0.5 is generally advised as a good trade off.
    """)
    parser.add_argument("-fd", "--free_dispersion", default = False, action="store_true", help = """
    Flag: Specify if the dispersion around the centroid vector of each partition is the same for all the organisms or if the dispersion is free
    """)
    parser.add_argument("-df", "--delete_nem_intermediate_files", default=False, action="store_true", help="""
    Flag: Delete intermediate files used by NEM""")
    parser.add_argument("-cg", "--compress_graph", default=False, action="store_true", help="""
    Flag: Compress (using gzip) the files containing the partionned pangenome graph""")
    parser.add_argument("-c", "--cpu", default=[1],  type=int, nargs=1, metavar=('NB_CPU'), help="""
    Positive Number: Number of cpu to use (several cpu will be used only if the option -e is set or/and if the -ck option is below the number of organisms provided)""")
    parser.add_argument("-v", "--verbose", default=False, action="store_true", help="""
    Flag: Show all messages including debugging ones""")
    # parser.add_argument("-as", "--already_sorted", default=False, action="store_true", help="""
    # Accelerate loading of gff files if there are sorted by the coordinate of gene annotations (starting point) for each contig""")
    #parser.add_argument("-l", "--freemem", default=False, action="store_true", help="""
    #Free the memory elements which are no longer used""")
    parser.add_argument("-p", "--plots", default=False, action="store_true", help="""
    Flag: Run the Rscript generating the plots (required: R in the path and the packages ggplot2, ggrepel, data.table, minpack.lm and reshape2 to be installed).""")
    # parser.add_argument("-di", "--directed", default=False, action="store_true", help="""
    # generate directed graph
    # """)
    parser.add_argument("-e", "--evolution", default=False, action="store_true", help="""
    Flag: Partition the pangenome using multiple subsamples of a croissant number of organisms in order to obtain a curve of the evolution of the pangenome metrics
    """)
    parser.add_argument("-ep", "--evolution_resampling_param", nargs=5, default=[0.1,10,30,1,float("Inf")], metavar=('RESAMPLING_RATIO','MINIMUM_RESAMPLING','MAXIMUM_RESAMPLING','STEP','LIMIT'), help="""
    5 Positive Numbers (or Inf for the last one):
    1st argument is the resampling ratio (FLOAT)
    2st argument is the minimum number of resampling for each number of organisms (INTEGER)
    3nd argument is the maximum number of resampling for each number of organisms (INTEGER or Inf)
    4rd argument is the step between each number of organisms (INTEGER)
    5rd argument is the limit of the size of the samples (INTEGER or Inf)
    """)
    parser.add_argument("-pr", "--projection", type = int, nargs = "+", metavar=('LINE_NUMBER_OR_ZERO'), help="""
    Positive Number: project the graph as a circos plot on each organism.
    Expected parameters are the line number (1 based) of each organism on which the graph will be projected.
    It provides a circular plot (well-assembled representative organisms must be prefered).
    0 means all organisms (it is discouraged to use -p and -pr 0 in the same time because the projection of the graph on all the organisms can take a long time).
    """)
    parser.add_argument("-ck", "--chunck_size", type = int, nargs = 1, default = [500], metavar=('SIZE'), help="""
    Positive Number: Size of the chunks to perform the partioning by chunks.
    If the number of organisms used is higher than SIZE, the partioning will be performed by chunks of size SIZE
    """)
    parser.add_argument("-mt", "--metadata", type=argparse.FileType('r'), default = [None], nargs=1, metavar=('METADATA_FILE'), help="""
    File: It is possible to add metainformation to the pangenome graph. These information must be associated to each organism via a METADATA_FILE. During the construction of the graph, metainformation about the organisms are used to label the covered edges.
    METADATA_FILE is a tab-delimitated file. The first line contains the names of the attributes and the following lines contain associated information for each organism (in the same order as in the ORGANISM_FILE).
    Metadata can't contain reserved word or exact organism name.
    """)
    parser.add_argument("-ss", "--subpartition_shell", default = 0, type=int, nargs=1, help = """
    Number: (in test) Subpartition the shell genome in k subpartitions, k can be detected automatically using k = -1, if k = 0 the partioning will used the first column of metadata to subpartition the shell""")
    parser.add_argument("-l", "--compute_layout", default = False, action="store_true", help = """
    Flag: (in test) precalculated the ForceAtlas2 layout""")

    global options
    options = parser.parse_args()

    level = logging.INFO
    if options.verbose:
        level = logging.DEBUG

    logging.basicConfig(stream=sys.stdout, level = level, format = '\n%(asctime)s %(filename)s:l%(lineno)d %(levelname)s\t%(message)s', datefmt='%Y-%m-%d %H:%M:%S')

    logging.getLogger().info("Command: "+" ".join([arg for arg in sys.argv]))
    logging.getLogger().info("PPanGGOLiN version: "+pkg_resources.get_distribution("ppanggolin").version)
    logging.getLogger().info("Python version: "+sys.version)
    logging.getLogger().info("Networkx version: "+nx.__version__)
    global OUTPUTDIR
    global TMP_DIR
    OUTPUTDIR       = options.output_directory[0]
    TMP_DIR         = options.temporary_directory[0]

    list_dir        = ["",FIGURE_DIR,PARTITION_DIR]
    if options.projection:
        list_dir.append(PROJECTION_DIR)
    if options.evolution:
        list_dir.append(EVOLUTION_DIR)
        (RESAMPLING_RATIO, RESAMPLING_MIN, RESAMPLING_MAX, STEP, LIMIT) = options.evolution_resampling_param
        (RESAMPLING_RATIO, RESAMPLING_MIN, RESAMPLING_MAX, STEP, LIMIT) = (float(RESAMPLING_RATIO), int(RESAMPLING_MIN), int(RESAMPLING_MAX) if str(RESAMPLING_MAX).upper() != "Inf" else sys.maxsize, int(STEP), int(LIMIT) if str(LIMIT).upper() != "INF" else sys.maxsize)
    for directory in list_dir:
        if not os.path.exists(OUTPUTDIR+directory):
            os.makedirs(OUTPUTDIR+directory)
        elif not options.force:
            logging.getLogger().error(OUTPUTDIR+directory+" already exist")
            exit(1)

    #-------------
    metadata = None

    if options.metadata[0]:
        metadata = list()
        attribute_names = list()
        for num, line in enumerate(options.metadata[0]):
            elements = [el.strip() for el in line.split("\t")]
            if num == 0:
                attribute_names = elements
            else:
                metadata.append(dict(zip(attribute_names,elements)))

    start_loading = time()
    global pan
    pan = PPanGGOLiN("file",
                     options.organisms[0],
                     options.gene_families[0],
                     options.remove_high_copy_number_families[0],
                     options.infer_singletons,
                     #options.directed)
                     False)

    

    # # if options.update is not None:
    # #     pan.import_from_GEXF(options.update[0])
    # end_loading_file = time.time()
    # #-------------

    # #-------------
    
    # start_neighborhood_computation = time.time()
    end_loading = time()
    #-------------

    #-------------
    logging.getLogger().info("Partitioning...")

    start_partitioning = time()
    pan.partition(nem_dir_path    = TMP_DIR+NEM_DIR,
                  organisms       = None,
                  beta            = options.beta_smoothing[0],
                  free_dispersion = options.free_dispersion,
                  chunck_size     = options.chunck_size[0],
                  inplace         = True,
                  just_stats      = False,
                  nb_threads      = options.cpu[0])
    end_partitioning = time()
    #-------------
    if options.metadata[0]:
        metadata = OrderedDict(zip(list(pan.organisms),metadata))

    if options.subpartition_shell:
        if options.subpartition_shell[0] <0:
            Q = pan.partition_shell(Q = "auto")
            logging.getLogger().info(str(Q)+" subpartitions has been used to subpartition the shell genome...")
        elif options.subpartition_shell[0]==0:
            init=defaultdict(set)
            for orgs, metad in metadata.items():
                init[metad].add(orgs)
            pan.partition_shell(init_using_qual=init)
        else:
            pan.partition_shell(options.subpartition_shell[0])

    

    #-------------
    # start_identify_communities = time.time()
    # pan.identify_communities_in_each_partition()
    # end_identify_communities = time.time()
    #pan.identify_shell_subpaths()
    #-------------

    #-------------
    # th = 100

    # cpt_partition = {}
    # for fam in pan.neighbors_graph.node:
    #     cpt_partition[fam]= {"persistent":0,"shell":0,"cloud":0}

    # cpt = 0
    # validated = set()
    # while(len(validated)<pan.pan_size):
    #     sample = pan.sample(n=100)
    #     sample.neighborhood_computation(options.undirected, light=True)
    #     sample.partition(EVOLUTION+"/"+str(cpt), float(50), options.free_dispersion)#options.beta_smoothing[0]
    #     cpt+=1
    #     for node,data in pan.neighbors_graph.nodes(data=True):
    #         cpt_partition[node][data["partition"]]+=1
    #         if sum(cpt_partition[node].values()) > th:
    #             validated.add(node)

    # for fam, data in cpt_partition.items():
    #     pan.neighbors_graph.nodes[fam]["partition_bis"]= max(data, key=data.get)


    # print(cpt_partition)
    #-------------

    #-------------
    start_writing_output_file = time()

    if options.compute_layout:
        pan.compute_layout(multiThreaded=options.cpu[0])

    #pan.tile_plot(OUTPUTDIR+FIGURE_DIR)
    logging.getLogger().info("Writing GEXF file")


    pan.export_to_GEXF(OUTPUTDIR+GRAPH_FILE_PREFIX+(".gz" if options.compress_graph else ""), options.compress_graph, metadata)
    logging.getLogger().info("Writing GEXF light file")
    pan.export_to_GEXF(OUTPUTDIR+GRAPH_FILE_PREFIX+"_light"+(".gz" if options.compress_graph else ""), options.compress_graph, metadata, False,False)
    with open(OUTPUTDIR+"/pangenome.txt","w") as pan_text:
        for partition, families in pan.partitions.items(): 
            file = open(OUTPUTDIR+PARTITION_DIR+"/"+partition+".txt","w")
            file.write("\n".join(families)+"\n")
            if partition == "core_exact" or partition == "accessory":
                pan_text.write("\n".join(families)+"\n")
            file.close()
    pan.write_matrix(OUTPUTDIR+MATRIX_FILES_PREFIX)
    if options.projection:
        logging.getLogger().info("Projection...")
        start_projection = time()
        pan.projection(OUTPUTDIR+PROJECTION_DIR, [pan.organisms.__getitem__(index-1) for index in options.projection] if options.projection[0] > 0 else list(pan.organisms))
        end_projection = time()
    end_writing_output_file = time()

    pan.ushaped_plot(OUTPUTDIR+FIGURE_DIR)
    del pan.annotations # no more required for the following process

    # print(pan.partitions_by_organisms)
    # partitions_by_organisms_file = open(OUTPUTDIR+"/partitions_by_organisms.txt","w")
    # exact_by_organisms_file = open(OUTPUTDIR+"/exacte_by_organisms.txt","w")
    # for org, partitions in pan.partitions_by_organisms.items(): 
    #     partitions_by_organisms_file.write(org+"\t"+str(len(partitions["persistent"]))+
    #                                            "\t"+str(len(partitions["shell"]))+
    #                                            "\t"+str(len(partitions["cloud"]))+"\n")
    #     exact_by_organisms_file.write(org+"\t"+str(len(partitions["core_exact"]))+
    #                                       "\t"+str(len(partitions["accessory"]))+"\n")
    # partitions_by_organisms_file.close()
    # exact_by_organisms_file.close()
    #-------------

    logging.getLogger().info(pan)
    with open(OUTPUTDIR+"/"+SUMMARY_STATS_FILE_PREFIX+".txt","w") as file_stats:
        file_stats.write(str(pan))
    #-------------

    if options.untangle>0:
        pan.untangle_neighbors_graph(options.untangle[0])
        pan.export_to_GEXF(OUTPUTDIR+GRAPH_FILE_PREFIX+(".gz" if options.compress_graph else ""), options.compress_graph, metadata,"untangled_neighbors_graph" )

    plot_Rscript(script_outfile = OUTPUTDIR+"/"+SCRIPT_R_FIGURE, verbose=options.verbose)

    if options.evolution:

        logging.getLogger().info("Evolution...")

        start_evolution = time()
        if not options.verbose:
            logging.disable(logging.INFO)# disable INFO message to not disturb the progess bar
            logging.disable(logging.WARNING)# disable WARNING message to not disturb the progess bar
        combinations = samplingCombinations(list(pan.organisms), sample_ratio=RESAMPLING_RATIO, sample_min=RESAMPLING_MIN, sample_max=RESAMPLING_MAX)
        
        global shuffled_comb
        shuffled_comb = combinations
        shuffled_comb = [OrderedSet(comb) for nb_org, combs in combinations.items() for comb in combs if nb_org%STEP == 0 and nb_org<=LIMIT]
        shuffle(shuffled_comb)

        global evol
        evol =  open(OUTPUTDIR+EVOLUTION_DIR+EVOLUTION_STATS_FILE_PREFIX+".txt","w")

        evol.write(",".join(["nb_org","persistent","shell","cloud","core_exact","accessory","pangenome"])+"\n")
        evol.write(",".join([str(pan.nb_organisms),    
                              str(len(pan.partitions["persistent"])),
                              str(len(pan.partitions["shell"])),
                              str(len(pan.partitions["cloud"])),
                              str(len(pan.partitions["core_exact"])),
                              str(len(pan.partitions["accessory"])),
                              str(len(pan.partitions["accessory"])+len(pan.partitions["core_exact"]))])+"\n")
        evol.flush()
        with ProcessPoolExecutor(options.cpu[0]) as executor:
            futures = [executor.submit(resample,i) for i in range(len(shuffled_comb))]
            for f in tqdm(as_completed(futures), total = len(shuffled_comb), unit = 'pangenome resampled'):
                ex = f.exception()
                if ex:
                    executor.shutdown(wait=False)
                    raise ex
        evol.close()

        end_evolution = time()
        logging.disable(logging.NOTSET)#restaure info and warning messages 

    # if options.new_genes_evolution:
    #     logging.getLogger().info("New genes evolution...")
    #     start_evolution = time()
    #     if not options.verbose:
    #         logging.disable(logging.INFO)# disable INFO message to not disturb the progess bar
    #         logging.disable(logging.WARNING)# disable WARNING message to not disturb the progess bar
        
        
    #         with ProcessPoolExecutor(options.cpu[0]) as executor:
    #             futures = [executor.submit(resample,i) for i in range(len(shuffled_comb))]

    #         for f in tqdm(as_completed(futures), total = len(shuffled_comb), unit = 'pangenome resampled'):
    #             ex = f.exception()
    #             if ex:
    #                 executor.shutdown(wait=False)
    #                 raise ex
    #     evol.close()

    #     end_evolution = time()
    #     logging.disable(logging.NOTSET)#restaure info and warning messages 
    #-------------

    logging.getLogger().info("\n"+
    "Execution time of loading and neighborhood computation: """ +str(round(end_loading-start_loading, 2))+" s\n"+
    #"Execution time of neighborhood computation: " +str(round(end_neighborhood_computation-start_neighborhood_computation, 2))+" s\n"+
    "Execution time of partitioning: " +str(round(end_partitioning-start_partitioning, 2))+" s\n"+
    #"Execution time of community identification: " +str(round(end_identify_communities-start_identify_communities, 2))+" s\n"+
    "Execution time of writing output files: " +str(round(end_writing_output_file-start_writing_output_file, 2))+" s\n"+
    (("Execution time of evolution: " +str(round(end_evolution-start_evolution, 2))+" s\n") if options.evolution else "")+

    "Total execution time: " +str(round(time()-start_loading, 2))+" s\n")

    logging.getLogger().info("""The pangenome computation is complete.""")

    if options.plots:
        logging.getLogger().info("Running R script generating plot")
        cmd = "Rscript "+OUTPUTDIR+SCRIPT_R_FIGURE
        logging.getLogger().info("""Several plots will be generated using R (in the directory: """+OUTPUTDIR+FIGURE_DIR+""").
    If R and the required package (ggplot2, reshape2, ggrepel(>0.6.6), data.table, minpack.lm) are not installed don't worry, the R script is saved in the directory. To generate the figures later, just use the following command :
    """+cmd)
        
        logging.getLogger().info(cmd)
        proc = subprocess.Popen(cmd, shell=True)
        proc.communicate()

    if options.delete_nem_intermediate_files:
        pan.delete_nem_intermediate_files()  

    logging.getLogger().info("Finished !")
    exit(0)

if __name__ == "__main__":
    __main__()