#!/usr/bin/env python3
# -*- coding: iso-8859-1 -*-

from collections import defaultdict, OrderedDict
from ordered_set import OrderedSet
import argparse
import logging
import random 
import time
import math
from random import shuffle
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
import sys
import networkx as nx
from ordered_set import OrderedSet
import numpy as np
from decimal import Decimal
from scipy.special import comb

from ppanggolin import *

__version__ = "0.0.1"

### PATH AND FILE NAME
OUTPUTDIR                  = None 
NEM_DIR                    = "/NEM_results/"
FIGURE_DIR                 = "/figures/"
PROJECTION_DIR             = "/projections/"
EVOLUTION_DIR              = "/evolutions/"
PARTITION_DIR              = "/partitions/"
GRAPH_FILE_PREFIX          = "/graph"
MATRIX_FILES_PREFIX        = "/matrix"
USHAPE_PLOT_PREFIX         = "/Ushaped_plot"
MATRIX_PLOT_PREFIX         = "/Presence_absence_matrix_plot"
EVOLUTION_CURVE_PREFIX     = "/evolution_curve"
EVOLUTION_STAT_FILE_PREFIX = "/stat_evol"
SCRIPT_R_FIGURE            = "/generate_plots.R"



# Calcul du nombre total de combinaisons uniques de n elements
def combinationTotalNb(size):
    return pow(2,size)-1

# Generation d'une sous-liste al<C3><A9>atoire de taille n
def randomSublist(items,n):
    item_array = np.array(items)
    index_array = np.arange(item_array.size)
    np.random.shuffle(index_array)
    ordered_index_array = sorted(index_array[:n])
    return list(item_array[ordered_index_array])

# Generation de toutes les combinaisons uniques (sans notion d'ordre) d'elements donnes
def exactCombinations(items):
    len_item  = len(items);
    combinations = defaultdict(list)
    for i in range(1, 1<<len_item):
            c = []
            for j in range(0, len_item):
                    if(i & (1 << j)):
                            c.append(items[j])
            combinations[len(c)].append(c)
    return combinations

# Echantillonage proportionnel d'un nombre donne de combinaisons (sans remise)
def samplingCombinations(items, sample_ratio, sample_min, sample_max=100, step = 1):
    samplingCombinationList = defaultdict(list)
    item_size = len(items)
    combTotNb = combinationTotalNb(item_size)
    for k in range(1, item_size+1, step):
        tmp_comb = []
        combNb = Decimal(comb(item_size, k))
        combNb = sys.float_info.max if combNb>sys.float_info.max else combNb # to avoid to reach infinit values
        combNb_sample = math.ceil(Decimal(combNb)/Decimal(sample_ratio))
        # Plus petit echantillonage possible pour un k donn<C3><A9> = sample_min
        if ((combNb_sample < sample_min) and k != item_size):
            combNb_sample = sample_min
        # Plus grand echantillonage possible
        if (sample_max != None and (combNb_sample > sample_max)):
            combNb_sample = sample_max
        
        i = 0;
        while(i < combNb_sample):
            comb_sub = randomSublist(items,k)
            # Echantillonnage sans remise
            if (comb_sub not in tmp_comb):
                tmp_comb.append(comb)
                samplingCombinationList[len(comb_sub)].append(comb_sub)
            i+=1
    return samplingCombinationList

# Generate list of combinations of organisms exaustively or following a binomial coeficient
def organismsCombinations(orgs, nbOrgThr, sample_ratio, sample_min, sample_max = 100, step = 1):
    if (len(orgs) <= nbOrgThr):
        comb_list = exactCombinations(orgs)
    else:
        comb_list = samplingCombinations(orgs, sample_ratio, sample_min, sample_max, step)
    return comb_list


def plot_Rscript(script_outfile, run_script = True):
    """
    run r script
    required the following package to be instaled : ggplot2, reshape2, data.table, ggrepel (last version)

    """

    rscript = """
#!/usr/bin/env R
options(show.error.locations = TRUE)

if(!require("ggplot2")) { install.packages("ggplot2", dep = TRUE,repos = "http://cran.us.r-project.org") }
library("ggplot2")
if(!require("reshape2")) { install.packages("reshape2", dep = TRUE,repos = "http://cran.us.r-project.org") }
library("reshape2")

color_chart = c(pangenome="black", "accessory"="#EB37ED", "core_exact" ="#FF2828", shell = "#00D860", persistent="#F7A507", cloud = "#79DEFF")

########################### START U SHAPED PLOT #################################

binary_matrix         <- read.table('"""+OUTPUTDIR+MATRIX_FILES_PREFIX+""".Rtab', header=TRUE, sep='\\t', check.names = FALSE)
data_header           <- c("Gene","Non-unique Gene name","Annotation","No. isolates","No. sequences","Avg sequences per isolate","Accessory Fragment","Genome Fragment","Order within Fragment","Accessory Order with Fragment","QC","Min group size nuc","Max group size nuc","Avg group size nuc") 
family_data           <- binary_matrix[,colnames(binary_matrix) %in% data_header]
binary_matrix         <- binary_matrix[,!(colnames(binary_matrix) %in% data_header)]
occurences            <- rowSums(binary_matrix)
classification_vector <- family_data$partition

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

########################### START RESENCE/ABSENCE MATRIX #################################

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
        theme(axis.text.x = element_text(angle = 90, hjust = 1, vjust = 0.5), panel.border = element_blank(), panel.background = element_blank())

ggsave('"""+OUTPUTDIR+FIGURE_DIR+MATRIX_PLOT_PREFIX+""".pdf', device = "pdf", plot)

########################### END PRESENCE/ABSENCE MATRIX #################################

########################### START EVOLUTION CURVE #################################

if(!require("ggrepel") || packageVersion("ggrepel") < "0.6.6") { install.packages("ggrepel", dep = TRUE, repos = "http://cran.us.r-project.org") }
library("ggrepel")

if(!require("data.table")) { install.packages("data.table", dep = TRUE,repos = "http://cran.us.r-project.org") }
library("data.table")

if (file.exists('"""+OUTPUTDIR+EVOLUTION_DIR+EVOLUTION_STAT_FILE_PREFIX+""".txt')){
    data <- read.table('"""+OUTPUTDIR+EVOLUTION_DIR+EVOLUTION_STAT_FILE_PREFIX+""".txt', header = TRUE)
    data <- melt(data, id = "nb_org")
    colnames(data) <- c("nb_org","partition","value")

    final_state = data[data$nb_org == max(data$nb_org,na.rm=T),]
    final_state = final_state[!duplicated(final_state), ]
    final <- structure(names = as.character(final_state$partition), as.integer(final_state$value))

    #gamma and kappa are calculated according to the Tettelin et al. 2008 approach
    median_by_nb_org <- setDT(data)[,list(med=as.numeric(median(value))), by=c("nb_org","partition")]
    colnames(median_by_nb_org) <- c("nb_org_comb","partition","med")

    for (part in as.character(final_state$partition)){
        regression  <- nls(med~kapa*(nb_org_comb^gama),median_by_nb_org[which(median_by_nb_org$partition == part),],start=list(kapa=1000,gama=1))
        coefficient <- coef(regression)
        final_state[final_state$partition == part,"formula" ] <- paste0("n == ", format(coefficient["kapa"],decimal.mark = ",",digits =2),"~N^{",format(coefficient["gama"],digits =2),"}")
    }

    plot <- ggplot(data = data, aes_string(x="nb_org",y="value", colour = "partition"))+
            ggtitle(bquote(list("Rarefaction curve. Heap's law parameters based on Tettelin et al. 2008 approach", n == kappa~N^gamma)))+
            geom_smooth(data        = median_by_nb_org[median_by_nb_org$partition %in% c("pangenome","shell","cloud","accessory", "persistent", "core_exact") ,],# 
                        mapping     = aes_string(x="nb_org_comb",y="med",colour = "partition"),
                        method      = "nls",
                        formula     = y~kapa*(x^gama),method.args =list(start=c(kapa=1000,gama=1)),
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
            ggplot2::theme(axis.text.x = element_text(angle = 90, hjust = 1, vjust = 0.5))
    
    ggsave('"""+OUTPUTDIR+FIGURE_DIR+EVOLUTION_CURVE_PREFIX+""".pdf', device = "pdf", width = (par("din")[1]*2) ,plot)

}
########################### END EVOLUTION CURVE #################################

########################### START PROJECTION #################################

for (org_csv in list.files(path = '"""+OUTPUTDIR+PROJECTION_DIR+"""', pattern = "*.csv$", full.names = T)){
    org_name <- tools::file_path_sans_ext(basename(org_csv))
    data <- read.table(org_csv, header = T)
    data <- cbind(data, pos = seq(nrow(data)))

    max_degree_log2p1 <- max(apply(data,1,FUN = function(x){
            sum(log2(as.numeric(x[6:8])+1))
        }))

    ori <- which(data$ori == T, arr.ind=T)
    data$ori <- NULL

    duplicated_fam     <- unique(data[duplicated(data$family),"family"])
    data$family <- ifelse(data$family %in% duplicated_fam, data$family, NA)
    data$family = as.factor(data$family)
    colors_duplicated_fam <- rainbow(length(duplicated_fam))
    names(colors_duplicated_fam) <- duplicated_fam

    data_melted <- melt(data, id.var=c("contig", "gene","family","partition","pos"))
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
                        axis.ticks.x       = ggplot2::element_blank(),
                        axis.title.x     = ggplot2::element_blank(),
                        panel.background = ggplot2::element_blank(),
                        panel.border     = ggplot2::element_blank(),
                        panel.grid.major.x = ggplot2::element_blank(),
                        panel.grid.minor.x = ggplot2::element_blank(),
                        plot.background  = ggplot2::element_blank(),
                        plot.margin      = grid::unit(c(0,0,0,0), "cm"),
                        panel.spacing    = grid::unit(c(0,0,0,0), "cm"))

    ggsave(paste0('"""+OUTPUTDIR+FIGURE_DIR+"""',org_name,'.pdf'), device = "pdf", height= 40, width = 49, plot)

}
########################### END PROJECTION #################################

    """
    logging.getLogger().info("Writing R script generating plot")
    with open(script_outfile,"w") as script_file:
        script_file.write(rscript)
    logging.getLogger().info("Running R script generating plot")
    if run_script:
        logging.getLogger().info("Rscript "+script_outfile)
        proc = subprocess.Popen("Rscript "+script_outfile, shell=True)
        proc.communicate()

#### START - NEED TO BE AT THE HIGHEST LEVEL OF THE MODULE TO ALLOW MULTIPROCESSING
shuffled_comb = []
evol = None
pan = None
options = None
EVOLUTION = None

def resample(index):
    global shuffled_comb
    stats = pan.partition(nem_dir_path    = OUTPUTDIR+EVOLUTION_DIR+"/nborg"+str(len(shuffled_comb[index]))+"_"+str(index),
                          organisms       = shuffled_comb[index],
                          beta            = options.beta_smoothing[0],
                          free_dispersion = options.free_dispersion,
                          chunck_size     = options.chunck_size[0],
                          inplace         = False,
                          just_stats      = True,
                          nb_threads      = 1)

    evol.write("\t".join([str(len(shuffled_comb[index])),
                          str(stats["persistent"]) if stats["undefined"] == 0 else "NA",
                          str(stats["shell"]) if stats["undefined"] == 0 else "NA",
                          str(stats["cloud"]) if stats["undefined"] == 0 else "NA",
                          str(stats["core_exact"]),
                          str(stats["accessory"]),
                          str(stats["core_exact"]+stats["accessory"])])+"\n")
    evol.flush()

#### END - NEED TO BE AT THE HIGHEST LEVEL OF THE MODULE TO ALLOW MULTIPROCESSING


def __main__():
    """
    --organims is a tab delimited files containg at least 2 mandatory fields by row and as many optional field as circular contig. Each row correspond to an organism to be added to the pangenome.
    Reserved words are : "id", "label", "name", "weight", "partition", "partition_exact"
    The first field is the organinsm name (id should be unique not contain any spaces, " or ' and reserved words).
    The second field is the gff file associated to the organism. This path can be abolute or relative. The gff file must contain an id feature for each CDS (id should be unique not contain any spaces, " or ' and reserved words).
    The next fields contain the name of perfectly assemble circular contigs (contig name must should be unique and not contain any spaces, " or ' and reserved words).
    example:

    """
    parser = argparse.ArgumentParser(prog = "ppanggolin",
                                     description='Build a partitioned pangenome graph from annotated genomes and gene families', 
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('-?', '--version', action='version', version=__version__)
    parser.add_argument('-o', '--organisms', type=argparse.FileType('r'), nargs=1, metavar=('ORGANISMS_FILE'), help="""
    A tab delimited file containg at least 2 mandatory fields by row and as many optional fields as the number of well assembled circular contigs. Each row correspond to an organism to be added to the pangenome.
    Reserved words are : "id", "label", "name", "weight", "partition", "partition_exact"
    The first field is the organinsm name (id should be unique not contain any spaces, " or ' and reserved words).
    The second field is the gff file associated to the organism. This path can be abolute or relative. The gff file must contain an id feature for each CDS (id should be unique across all pangenome and not contain any spaces, " or ' and reserved words).
    The next fields contain the name of perfectly assembled circular contigs.
    Contig names should be unique and not contain any spaces, quote, double quote and reserved words.
    example:""", required=True)
    parser.add_argument('-gf', '--gene_families', type=argparse.FileType('r'), nargs=1, metavar=('FAMILIES_FILE'), help="""
    A tab delimited file containg the gene families. Each row contain 2 fields.
    Reserved words are : "id", "label", "name", "weight", "partition", "partition_exact"
    The first field is the family name.
    The second field is the gene name.
    families are intended to be grouped by chuncks of row.
    the families name can be any string but must should be unique and not contain any spaces, " or ' and reserved words
    As a conventation, it is recommanded to use the name of the most reprensative gene of the families as the family name.
    Gene name can be any string corresponding to the if feature in the gff files. they should be unique and not contain any spaces, " or ' and reserved words.
    example:""",  required=True)
    parser.add_argument('-od', '--output_directory', type=str, nargs=1, default=["output.dir"], metavar=('OUTPUT_DIR'), help="""
    The output directory""")
    parser.add_argument('-f', '--force', action="store_true", help="""
    Force overwriting existing output directory""")
    parser.add_argument('-r', '--remove_high_copy_number_families', type=int, nargs=1, default=[0], metavar=('REPETITION_THRESHOLD'), help="""
    Remove families having a number of copy of one families above or equal to this threshold in at least one organism (0 or negative value keep all families whatever their occurence). 
    When -u is set, only work on new organisms added""")
    parser.add_argument('-s', '--infere_singleton', default=False, action="store_true", help="""
    If a gene id found in a gff file is absent of the gene families file, the singleton will be automatically infered as a gene families having a single element. 
    if this argument is not set, the program will raise KeyError exception if a gene id found in a gff file is absent of the gene families file.""")
    #    parser.add_argument("-u", "--update", default = None, type=argparse.FileType('r'), nargs=1, help="""
    # Pangenome Graph to be updated (in gexf format)""")
    parser.add_argument("-b", "--beta_smoothing", default = [float("0.5")], type=float, nargs=1, metavar=('BETA_VALUE'), help = """
    Coeficient of smoothing all the partionning based on the Markov Random Feild leveraging the weigthed pangenome graph. A positive float, 0.0 means to discard spatial smoothing and 1.00 means strong smoothing (can be more but it is not advised), 0.5 is generally advised as a good trad off.
    """)
    parser.add_argument("-fd", "--free_dispersion", default = False, action="store_true", help = """
    Specify if the dispersion around the centroid vector of each paritition is the same for all the organisms or if the dispersion is free
    """)
    parser.add_argument("-df", "--delete_nem_intermediate_files", default=False, action="store_true", help="""
    Delete intermediate files used by NEM. Do not delete these files if you can the gerate plot latter using the generated Rscript""")
    parser.add_argument("-cg", "--compress_graph", default=False, action="store_true", help="""
    Compress (using gzip) the file containing the partionned pangenome graph""")
    parser.add_argument("-c", "--cpu", default=[1],  type=int, nargs=1, metavar=('NB_CPU'), help="""
    Number of cpu to use""")
    parser.add_argument("-ss", "--subpartition_shell", default = 0, type=int, nargs=1, help = """
    Subpartition the shell genome in n subpartition, n can be ajusted automatically if n = -1, 0 desactivate shell genome subpartitioning""")
    parser.add_argument("-v", "--verbose", default=False, action="store_true", help="""
    Show all messages including debug ones""")
    # parser.add_argument("-as", "--already_sorted", default=False, action="store_true", help="""
    # Accelerate loading of gff files if there are sorted by the coordinate of gene annotations (starting point) for each contig""")
    parser.add_argument("-l", "--ligth", default=False, action="store_true", help="""
    Free the memory elements which are no longer used""")
    parser.add_argument("-p", "--plots", default=False, action="store_true", help="""
    Generate Rscript able to draw plots and run it. (required R in the path and the packages ggplot2, ggrepel, data.table and reshape2 to be installed)""")
    parser.add_argument("-ud", "--undirected", default=False, action="store_true", help="""
    generate undirected graph
    """)
    parser.add_argument("-e", "--evolution", default=False, action="store_true", help="""
    Relaunch the script using less and less organism in order to obtain a curve of the evolution of the pangenome metrics
    """)
    parser.add_argument("-ep", "--evolution_resampling_param", nargs=4, default=[0.1,10,30,1], metavar=('RESAMPLING_RATIO','MINIMUN_RESAMPLING','MAXIMUN_RESAMPLING','STEP'), help="""
    1st argument is the resampling ratio (FLOAT)
    2st argument is the minimun number of resampling for each number of organisms (INTEGER)
    3nd argument is the maximun number of resampling for each number of organisms (INTEGER)
    4rd argument is the step between each number of organisms (INTEGER)
    """)
    parser.add_argument("-pr", "--projection", type = int, nargs = "+", metavar=('LINE_NUMBER_OR_ZERO'), help="""
    Project the graph as a circos plot on each organism.
    Expected parameters are the line number (1 based) of each organism on which the graph will be projected providing a circos plot (well assembled representative organisms must be prefered).
    0 means all organisms (it is discouraged to use -p and -pr 0 in the same time because the projection of the graph on all the organisms can take a long time).
    """)
    parser.add_argument("-ck", "--chunck_size", type = int, nargs = 1, default = [200], metavar=('SIZE'), help="""
    Size of the chunks to performs multiple resampling
    """)
    global options
    options = parser.parse_args()

    level = logging.INFO
    if options.verbose:
        level = logging.DEBUG

    logging.basicConfig(stream=sys.stdout, level = level, format = '\n%(asctime)s %(filename)s:l%(lineno)d %(levelname)s\t%(message)s', datefmt='%H:%M:%S')

    logging.getLogger().info("Command: "+" ".join([arg for arg in sys.argv]))
    logging.getLogger().info("Python version: "+sys.version)
    logging.getLogger().info("Networkx version: "+nx.__version__)
    global OUTPUTDIR
    OUTPUTDIR       = options.output_directory[0]

    list_dir        = [NEM_DIR,FIGURE_DIR,PARTITION_DIR]
    if options.projection:
        list_dir.append(PROJECTION_DIR)
    if options.evolution:
        list_dir.append(EVOLUTION_DIR)
        (RESAMPLING_RATIO, RESAMPLING_MIN, RESAMPLING_MAX, STEP) = options.evolution_resampling_param
        (RESAMPLING_RATIO, RESAMPLING_MIN, RESAMPLING_MAX, STEP) = (float(RESAMPLING_RATIO), int(RESAMPLING_MIN), int(RESAMPLING_MAX), int(STEP))
    for directory in list_dir:
        if not os.path.exists(directory):
            os.makedirs(OUTPUTDIR+directory)
        elif not options.force:
            logging.getLogger().error(OUTPUTDIR+directory+" already exist")
            exit(1)

    #-------------
    start_loading = time.time()
    global pan
    pan = PPanGGOLiN("file",
                     options.organisms[0],
                     options.gene_families[0],
                     options.remove_high_copy_number_families[0],
                     options.infere_singleton,
                     options.undirected)

    # # if options.update is not None:
    # #     pan.import_from_GEXF(options.update[0])
    # end_loading_file = time.time()
    # #-------------

    # #-------------
    
    # start_neighborhood_computation = time.time()
    # #pan.neighborhood_computation(options.undirected, options.ligth)
    end_loading = time.time()
    #-------------

    #-------------
    logging.getLogger().info("Partitionning...")

    start_partitioning = time.time()
    pan.partition(nem_dir_path    = OUTPUTDIR+NEM_DIR,
                  beta            = options.beta_smoothing[0],
                  free_dispersion = options.free_dispersion,
                  chunck_size     = options.chunck_size[0],
                  inplace         = True,
                  nb_threads      = options.cpu[0])
    end_partitioning = time.time()
    #-------------

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
    start_writing_output_file = time.time()

    pan.ushaped_plot(OUTPUTDIR+FIGURE_DIR)
    #pan.tile_plot(OUTPUTDIR+FIGURE_DIR)
    print(OUTPUTDIR+GRAPH_FILE_PREFIX+(".gz" if options.compress_graph else ""))
    pan.export_to_GEXF(OUTPUTDIR+GRAPH_FILE_PREFIX+(".gz" if options.compress_graph else ""), options.compress_graph)
    for partition, families in pan.partitions.items(): 
        file = open(OUTPUTDIR+PARTITION_DIR+"/"+partition+".txt","w")
        file.write("\n".join(families))
        file.close()
    pan.write_matrix(OUTPUTDIR+MATRIX_FILES_PREFIX)
    if options.projection:
        logging.getLogger().info("Projection...")
        start_projection = time.time()
        pan.projection_polar_histogram(OUTPUTDIR+PROJECTION_DIR, [pan.organisms.__getitem__(index-1) for index in options.projection] if options.projection[0] > 0 else list(pan.organisms))
        end_projection = time.time()
    end_writing_output_file = time.time()

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

    #-------------
    if options.evolution:

        logging.getLogger().info("Evolution...")

        start_evolution = time.time()
        logging.disable(logging.INFO)# disable message info to not disturb the progess bar
        combinations = organismsCombinations(list(pan.organisms), nbOrgThr=1, sample_ratio=RESAMPLING_RATIO, sample_min=RESAMPLING_MIN, sample_max=RESAMPLING_MAX)
        
        del combinations[pan.nb_organisms]
        del combinations[1]
        global shuffled_comb
        shuffled_comb = combinations
        shuffled_comb = [OrderedSet(comb) for nb_org, combs in combinations.items() for comb in combs if nb_org%STEP == 0]
        random.shuffle(shuffled_comb)

    
        global evol
        evol =  open(OUTPUTDIR+EVOLUTION_DIR+EVOLUTION_STAT_FILE_PREFIX+".txt","w")

        evol.write("nb_org\tpersistent\tshell\tcloud\tcore_exact\taccessory\tpangenome\n")
        evol.write("\t".join([str(pan.nb_organisms),
                                      str(len(pan.partitions["persistent"])),
                                      str(len(pan.partitions["shell"])),
                                      str(len(pan.partitions["cloud"])),
                                      str(len(pan.partitions["core_exact"])),
                                      str(len(pan.partitions["accessory"])),
                                      str(len(pan.partitions["accessory"])+len(pan.partitions["core_exact"]))])+"\n")
        evol.flush()

        with ProcessPoolExecutor(options.cpu[0]) as executor:
            futures = [executor.submit(resample,i) for i in range(len(shuffled_comb))]

            for f in tqdm(as_completed(futures), total = len(shuffled_comb), unit = 'pangenome resampled',  unit_scale = True):
                if f.exception() is not None:
                    logging.getLogger().error(f.exception())
                    executor.shutdown(wait=False)
                    exit(1)

        evol.close()

        end_evolution = time.time()
        logging.disable(logging.NOTSET)#restaure message info
    #-------------

    logging.getLogger().info("\n"+
    "Execution time of loading: """ +str(round(end_loading-start_loading, 2))+" s\n"+
    #"Execution time of neighborhood computation: " +str(round(end_neighborhood_computation-start_neighborhood_computation, 2))+" s\n"+
    "Execution time of partitioning: " +str(round(end_partitioning-start_partitioning, 2))+" s\n"+
    #"Execution time of community identification: " +str(round(end_identify_communities-start_identify_communities, 2))+" s\n"+
    "Execution time of writing output files: " +str(round(end_writing_output_file-start_writing_output_file, 2))+" s\n"+
    (("Execution time of evolution: " +str(round(end_evolution-start_evolution, 2))+" s\n") if options.evolution else "")+

    "Total execution time: " +str(round(time.time()-start_loading, 2))+" s\n")

    logging.getLogger().info("""
    The pangenome computation is complete. 
    Plots will be generated using R (in the directory: """+OUTPUTDIR+FIGURE_DIR+""").
    If R and the required package (ggplot2, reshape2, ggrepel(>0.6.6), data.table) are not instaled don't worry the R script will be saved in the directory allowing to generate the figures latter""")

    plot_Rscript(script_outfile           = OUTPUTDIR+"/"+SCRIPT_R_FIGURE,
                 run_script               = options.plots)

    if options.delete_nem_intermediate_files:
            pan.delete_nem_intermediate_files()  

    logging.getLogger().info("Finished !")
    exit(0)

if __name__ == "__main__":
    __main__()